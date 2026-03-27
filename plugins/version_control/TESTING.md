# Version Control Plugin - Testing Documentation

This document describes the test coverage for the Version Control Plugin.

## Test Files

### 1. `core/test_version_control_core.py`
Tests for the core version control logic.

**Test Classes:**
- `TestHashComputer` - Hash computation tests
- `TestVersionControlDB` - Database management tests  
- `TestVersionControlCore` - Core business logic tests

**Coverage:**

#### HashComputer Tests (11 tests)
- ✅ `test_compute_tools_hash_empty_list` - Empty tools list handling
- ✅ `test_compute_tools_hash_single_tool` - Single tool hashing
- ✅ `test_compute_tools_hash_multiple_tools` - Multiple tools hashing
- ✅ `test_compute_tools_hash_deterministic` - Hash determinism
- ✅ `test_compute_tools_hash_order_independent` - Order independence
- ✅ `test_compute_tools_hash_different_tools_different_hash` - Collision resistance
- ✅ `test_compute_tools_hash_schema_changes_affect_hash` - Schema change detection
- ✅ `test_compute_version_hash_basic` - Basic version hash
- ✅ `test_compute_version_hash_deterministic` - Version hash determinism
- ✅ `test_compute_version_hash_different_version_different_hash` - Version changes
- ✅ `test_compute_version_hash_different_tools_different_hash` - Tools changes

#### VersionControlDB Tests (4 tests)
- ✅ `test_init_creates_engines` - Engine initialization
- ✅ `test_create_tables_success` - Table creation
- ✅ `test_get_main_session_returns_session` - Main DB session
- ✅ `test_get_vc_session_returns_session` - Version control DB session

#### VersionControlCore Tests (7 tests)
- ✅ `test_init_creates_hash_computer` - Initialization
- ✅ `test_discover_existing_servers_empty` - Server discovery (empty)
- ✅ `test_create_initial_version_with_mocked_server` - Initial version creation
- ✅ `test_check_for_changes_no_existing_version` - Change detection (no version)
- ✅ `test_check_for_changes_detects_tool_addition` - Change detection (tools added)
- ✅ `test_check_for_changes_no_changes` - Change detection (no changes)
- ✅ `test_create_pending_version_increments_version_number` - Version numbering
- ✅ `test_update_version_status_to_active` - Status transition to active
- ✅ `test_update_version_status_to_deactivated` - Status transition to deactivated

**Total: 22 tests**

### 2. `test_version_control_plugin.py`
Tests for the main plugin class and security-critical hooks.

**Test Classes:**
- `TestVersionControlPluginInit` - Plugin initialization tests
- `TestVersionControlPluginInitialize` - Async initialization tests
- `TestVersionControlPluginToolPreInvoke` - **CRITICAL** Security hook tests
- `TestVersionControlPluginShutdown` - Shutdown behavior tests
- `TestVersionControlPluginGetStatus` - Status reporting tests

**Coverage:**

#### Plugin Initialization Tests (3 tests)
- ✅ `test_init_with_valid_config` - Valid configuration
- ✅ `test_init_disabled_when_missing_db_urls` - Missing DB URLs
- ✅ `test_init_with_custom_polling_interval` - Custom polling interval

#### Async Initialization Tests (2 tests)
- ✅ `test_initialize_performs_backfill` - Initial server backfill
- ✅ `test_initialize_disabled_plugin_does_nothing` - Disabled plugin behavior

#### Tool Pre-Invoke Hook Tests (8 tests) - **SECURITY CRITICAL**
- ✅ `test_tool_pre_invoke_allows_active_server` - Allow active servers
- ✅ `test_tool_pre_invoke_blocks_deactivated_server` - Block deactivated servers
- ✅ `test_tool_pre_invoke_blocks_pending_changes` - Block pending changes
- ✅ `test_tool_pre_invoke_detects_and_blocks_new_changes` - Real-time change detection
- ✅ `test_tool_pre_invoke_creates_initial_version_for_new_server` - New server handling
- ✅ `test_tool_pre_invoke_disabled_plugin_allows_all` - Disabled plugin bypass
- ✅ `test_tool_pre_invoke_no_server_id_allows_call` - Missing server_id (fail open)

#### Shutdown Tests (1 test)
- ✅ `test_shutdown_cancels_polling_task` - Proper cleanup

#### Status Tests (1 test)
- ✅ `test_get_status_returns_correct_info` - Status reporting

**Total: 15 tests**

## Running Tests

### Run All Version Control Plugin Tests
```bash
# From project root
pytest plugins/version_control/ -v

# With coverage
pytest plugins/version_control/ --cov=plugins/version_control --cov-report=html
```

### Run Specific Test Files
```bash
# Core logic tests only
pytest plugins/version_control/core/test_version_control_core.py -v

# Plugin tests only
pytest plugins/version_control/test_version_control_plugin.py -v
```

### Run Specific Test Classes
```bash
# Hash computation tests
pytest plugins/version_control/core/test_version_control_core.py::TestHashComputer -v

# Security hook tests
pytest plugins/version_control/test_version_control_plugin.py::TestVersionControlPluginToolPreInvoke -v
```

### Run Specific Tests
```bash
# Test that deactivated servers are blocked
pytest plugins/version_control/test_version_control_plugin.py::TestVersionControlPluginToolPreInvoke::test_tool_pre_invoke_blocks_deactivated_server -v
```

## Test Coverage Summary

| Component | Tests | Coverage Focus |
|-----------|-------|----------------|
| HashComputer | 11 | Hash determinism, collision resistance |
| VersionControlDB | 4 | Database initialization, session management |
| VersionControlCore | 7 | Change detection, version management |
| VersionControlPlugin | 15 | Security hooks, initialization, shutdown |
| **TOTAL** | **37** | **Comprehensive coverage** |

## Critical Security Tests

The following tests verify security-critical blocking behavior:

1. **Deactivated Server Blocking** - `test_tool_pre_invoke_blocks_deactivated_server`
   - Ensures deactivated servers cannot execute tools
   - Returns violation code: `VERSION_CONTROL_DEACTIVATED`

2. **Pending Changes Blocking** - `test_tool_pre_invoke_blocks_pending_changes`
   - Ensures servers with unapproved changes are blocked
   - Returns violation code: `VERSION_CONTROL_PENDING`

3. **Real-time Change Detection** - `test_tool_pre_invoke_detects_and_blocks_new_changes`
   - Detects changes before tool execution
   - Creates pending version and blocks call
   - Returns violation code: `VERSION_CONTROL_CHANGES_DETECTED`

4. **Active Server Allow** - `test_tool_pre_invoke_allows_active_server`
   - Verifies active servers with no changes are allowed
   - Returns metadata: `version_control_check: passed`

## Test Dependencies

Tests use the following mocking strategies:

- **Database**: SQLite in-memory or temporary files
- **MCP Calls**: AsyncMock for `get_server_info`, `compute_hashes_for_gateway`
- **Sessions**: MagicMock for database sessions
- **Async Operations**: pytest-asyncio for async test support

## Future Test Additions

Consider adding tests for:

1. **Concurrent Access** - Multiple simultaneous version checks
2. **Database Failures** - Error handling and recovery
3. **MCP Protocol Errors** - Network failures, timeouts
4. **Polling Loop** - Background task behavior
5. **Version History** - Multiple version transitions
6. **Performance** - Hash computation speed, database query optimization

## Test Maintenance

When modifying the plugin:

1. **Add tests first** (TDD approach)
2. **Run existing tests** to ensure no regressions
3. **Update this documentation** with new test coverage
4. **Maintain >80% code coverage** target
5. **Focus on security-critical paths** (tool_pre_invoke hook)

## Debugging Failed Tests

```bash
# Run with verbose output and print statements
pytest plugins/version_control/ -v -s

# Run with debugger on failure
pytest plugins/version_control/ --pdb

# Run with coverage and show missing lines
pytest plugins/version_control/ --cov=plugins/version_control --cov-report=term-missing