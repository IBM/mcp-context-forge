# Vault Integration Testing Guide

## Overview

This guide explains how to run integration tests for the Vault token storage backend using a real HashiCorp Vault instance.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.13+
- Virtual environment activated

## Quick Start

```bash
# 1. Start Vault test instance
docker-compose -f docker-compose.vault-test.yml up -d

# 2. Wait for Vault to be ready (10-15 seconds)
sleep 15

# 3. Run integration tests
pytest tests/integration/test_vault_integration.py -v

# 4. Stop Vault when done
docker-compose -f docker-compose.vault-test.yml down
```

## Detailed Setup

### 1. Start Vault Test Environment

```bash
# Start Vault in development mode
docker-compose -f docker-compose.vault-test.yml up -d

# Check Vault status
docker ps | grep vault-test

# View Vault logs
docker logs contextforge-vault-test
```

**Vault Test Instance Details:**
- **URL:** http://localhost:8200
- **Root Token:** `test-root-token`
- **Mode:** Development (in-memory, unsealed)
- **KV Engine:** v2 (mounted at `secret/`)

⚠️ **Warning:** This is a development instance. **Never use in production!**

### 2. Verify Vault is Ready

```bash
# Check Vault health
curl http://localhost:8200/v1/sys/health

# Expected output:
# {"initialized":true,"sealed":false,"standby":false,...}

# Verify authentication
curl -H "X-Vault-Token: test-root-token" \
     http://localhost:8200/v1/auth/token/lookup-self

# Expected: 200 OK with token details
```

### 3. Set Environment Variables

```bash
# Required for integration tests
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=test-root-token

# Optional: Use PostgreSQL instead of SQLite
export TEST_DATABASE_URL=postgresql+psycopg://test_user:test_password@localhost:5433/mcp_test
```

### 4. Run Integration Tests

```bash
# Run all Vault integration tests
pytest tests/integration/test_vault_integration.py -v

# Run specific test class
pytest tests/integration/test_vault_integration.py::TestVaultIntegrationTokenStorage -v

# Run with detailed output
pytest tests/integration/test_vault_integration.py -vv -s

# Run with coverage
pytest tests/integration/test_vault_integration.py \
       --cov=mcpgateway.services.token_backends.vault_backend \
       --cov-report=html
```

## Test Structure

### Test Classes

1. **TestVaultIntegrationBasics** (3 tests)
   - Vault connectivity
   - Authentication
   - KV v2 mount verification

2. **TestVaultIntegrationTokenStorage** (7 tests)
   - Store and retrieve tokens
   - Store without refresh token
   - Store without expiry
   - Update existing token
   - Token isolation by team
   - Token isolation by user

3. **TestVaultIntegrationTokenRetrieval** (3 tests)
   - Get non-existent token
   - Get token metadata
   - Get token info for missing token

4. **TestVaultIntegrationTokenRevocation** (2 tests)
   - Revoke existing token
   - Revoke non-existent token

5. **TestVaultIntegrationCaching** (2 tests)
   - Cache reduces Vault calls
   - Cache invalidation on update

6. **TestVaultIntegrationErrorHandling** (2 tests)
   - Gateway not found error
   - Special characters in email

7. **TestVaultIntegrationCleanup** (1 test)
   - Cleanup expired tokens

**Total: 20 integration tests**

## Test Coverage

### What's Tested

✅ **Real Vault Interactions**
- HTTP API calls to actual Vault instance
- KV v2 read/write/delete operations
- Authentication and authorization
- Path construction and URL encoding

✅ **Token Lifecycle**
- Store tokens (with/without refresh token)
- Retrieve valid tokens
- Update existing tokens
- Revoke tokens

✅ **Multi-tenancy**
- Token isolation by team_id
- Token isolation by user email
- Different teams accessing same gateway

✅ **Caching**
- Cache hit on repeated reads
- Cache invalidation on updates
- Cache key construction

✅ **Error Handling**
- Non-existent gateway
- Non-existent token (404)
- Special characters in identifiers

### What's NOT Tested

❌ **Vault Security Features** (future work)
- Vault policies and ACLs
- Vault namespaces (Enterprise)
- Token TTL expiration
- Vault audit logs

❌ **Production Scenarios** (future work)
- TLS/SSL connections
- AppRole authentication
- High availability
- Performance under load

❌ **Token Refresh** (future work)
- OAuth token refresh flow
- Refresh token rotation
- Token expiry handling

## Running Tests in CI/CD

### GitHub Actions

```yaml
name: Vault Integration Tests

on: [push, pull_request]

jobs:
  vault-integration:
    runs-on: ubuntu-latest
    
    services:
      vault:
        image: hashicorp/vault:1.15
        env:
          VAULT_DEV_ROOT_TOKEN_ID: test-root-token
          VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
        ports:
          - 8200:8200
        options: >-
          --health-cmd "vault status"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e .[dev]
      
      - name: Wait for Vault to be ready
        run: |
          timeout 30 bash -c 'until curl -sf http://localhost:8200/v1/sys/health; do sleep 2; done'
      
      - name: Run Vault integration tests
        env:
          VAULT_ADDR: http://localhost:8200
          VAULT_TOKEN: test-root-token
        run: |
          pytest tests/integration/test_vault_integration.py -v
```

### GitLab CI

```yaml
vault-integration:
  image: python:3.13
  
  services:
    - name: hashicorp/vault:1.15
      alias: vault
      variables:
        VAULT_DEV_ROOT_TOKEN_ID: test-root-token
        VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
  
  variables:
    VAULT_ADDR: http://vault:8200
    VAULT_TOKEN: test-root-token
  
  before_script:
    - pip install -e .[dev]
    - until curl -sf $VAULT_ADDR/v1/sys/health; do sleep 2; done
  
  script:
    - pytest tests/integration/test_vault_integration.py -v
```

## Troubleshooting

### Vault Container Not Starting

```bash
# Check Docker logs
docker logs contextforge-vault-test

# Verify port is not in use
lsof -i :8200

# Restart container
docker-compose -f docker-compose.vault-test.yml restart vault-test
```

### Tests Skipped with "Vault not available"

```bash
# Verify Vault is accessible
curl http://localhost:8200/v1/sys/health

# Check environment variables
echo $VAULT_ADDR
echo $VAULT_TOKEN

# Try manual connection
python -c "import httpx; print(httpx.get('http://localhost:8200/v1/sys/health').json())"
```

### Connection Refused Errors

```bash
# Wait longer for Vault to initialize
sleep 20

# Check Vault container status
docker ps -a | grep vault-test

# Restart Vault if needed
docker-compose -f docker-compose.vault-test.yml down
docker-compose -f docker-compose.vault-test.yml up -d
sleep 15
```

### Database Errors

```bash
# If using PostgreSQL, start it first
docker-compose -f docker-compose.vault-test.yml up -d postgres-test

# Verify PostgreSQL is ready
docker exec contextforge-postgres-test pg_isready

# Check connection
psql postgresql://test_user:test_password@localhost:5433/mcp_test -c '\l'
```

### Permission Denied Errors

```bash
# Check file permissions
ls -la docker-compose.vault-test.yml
ls -la tests/integration/test_vault_integration.py

# Verify you're in the project root
pwd  # Should be /Users/rakhidutta/mcp-context-forge
```

## Test Isolation

Each test uses fixtures for proper isolation:

- **`db_session`**: Fresh database session per test
- **`test_gateway`**: New gateway record per test
- **`vault_backend`**: New backend instance per test
- **`cleanup_vault_data`**: Cleanup after each test

This ensures tests don't interfere with each other.

## Performance

Typical test execution times:

- **Test Suite**: ~5-10 seconds
- **Per Test**: ~200-500ms
- **Vault API Call**: ~10-50ms
- **Database Query**: ~1-5ms

Integration tests are slower than unit tests but still fast enough for CI/CD.

## Best Practices

### DO

✅ Use the provided Docker Compose setup
✅ Wait for Vault health check before running tests
✅ Clean up containers after testing
✅ Use fixtures for test isolation
✅ Run integration tests before deploying
✅ Keep test data separate from production

### DON'T

❌ Use development Vault in production
❌ Share root token in production
❌ Skip cleanup steps
❌ Hardcode credentials in tests
❌ Run tests against production Vault
❌ Commit `.env` files with real credentials

## Makefile Targets

Add these to your `Makefile`:

```makefile
.PHONY: vault-test-start
vault-test-start:
	@echo "Starting Vault test environment..."
	docker-compose -f docker-compose.vault-test.yml up -d
	@echo "Waiting for Vault to be ready..."
	@sleep 15
	@echo "Vault ready at http://localhost:8200"

.PHONY: vault-test-stop
vault-test-stop:
	@echo "Stopping Vault test environment..."
	docker-compose -f docker-compose.vault-test.yml down

.PHONY: test-vault-integration
test-vault-integration: vault-test-start
	@echo "Running Vault integration tests..."
	VAULT_ADDR=http://localhost:8200 \
	VAULT_TOKEN=test-root-token \
	pytest tests/integration/test_vault_integration.py -v
	@$(MAKE) vault-test-stop

.PHONY: test-vault-integration-coverage
test-vault-integration-coverage: vault-test-start
	@echo "Running Vault integration tests with coverage..."
	VAULT_ADDR=http://localhost:8200 \
	VAULT_TOKEN=test-root-token \
	pytest tests/integration/test_vault_integration.py \
	       --cov=mcpgateway.services.token_backends.vault_backend \
	       --cov-report=term-missing --cov-report=html
	@$(MAKE) vault-test-stop
```

### Usage

```bash
# Start Vault
make vault-test-start

# Run tests (with auto start/stop)
make test-vault-integration

# Run with coverage
make test-vault-integration-coverage

# Stop Vault
make vault-test-stop
```

## Example Test Session

```bash
$ make test-vault-integration

Starting Vault test environment...
[+] Running 2/2
 ✔ Container contextforge-vault-test  Started  0.5s
 ✔ Container contextforge-postgres-test  Started  0.5s
Waiting for Vault to be ready...
Vault ready at http://localhost:8200

Running Vault integration tests...
============================= test session starts ==============================
platform darwin -- Python 3.13.12, pytest-9.1.0
collected 20 items

tests/integration/test_vault_integration.py::TestVaultIntegrationBasics::test_vault_is_reachable PASSED [ 5%]
tests/integration/test_vault_integration.py::TestVaultIntegrationBasics::test_vault_authentication_works PASSED [ 10%]
tests/integration/test_vault_integration.py::TestVaultIntegrationBasics::test_vault_kv_v2_mount_exists PASSED [ 15%]
tests/integration/test_vault_integration.py::TestVaultIntegrationTokenStorage::test_store_and_retrieve_token PASSED [ 20%]
... (16 more tests) ...

======================== 20 passed, 1 warning in 8.24s =========================

Stopping Vault test environment...
[+] Running 3/3
 ✔ Container contextforge-postgres-test  Removed  0.3s
 ✔ Container contextforge-vault-test  Removed  0.3s
 ✔ Network contextforge_vault-test-network  Removed  0.1s
```

## Security Considerations

### Development Mode

The test Vault instance runs in **development mode**:

- ✅ Good for testing
- ✅ Fast startup
- ✅ No persistence needed
- ❌ **Never use in production**
- ❌ Data lost on restart
- ❌ Single unsealed instance
- ❌ No audit logging

### Test Credentials

- **Root Token**: `test-root-token`
  - Only for testing
  - Never commit to version control
  - Rotate after testing

- **PostgreSQL**: `test_user` / `test_password`
  - Only for testing
  - Local access only
  - Isolated test database

## Next Steps

### Expand Test Coverage

1. **Token Refresh Tests**
   - Test OAuth token refresh flow
   - Test refresh token rotation
   - Test expired token handling

2. **Security Tests**
   - Test Vault policies
   - Test namespace isolation (Enterprise)
   - Test audit logging

3. **Performance Tests**
   - Test concurrent token operations
   - Test cache performance
   - Test bulk operations

4. **Error Recovery Tests**
   - Test Vault connection failures
   - Test retry logic
   - Test circuit breaker behavior

### Production Readiness

1. **Vault Production Setup**
   - Use production Vault (sealed, HA)
   - Configure AppRole authentication
   - Set up proper policies
   - Enable audit logging
   - Use TLS/SSL

2. **Integration Testing**
   - Test against staging Vault
   - Test failover scenarios
   - Test backup/restore
   - Load testing

## Summary

- ✅ **20 integration tests** covering real Vault interactions
- ✅ **Docker Compose** setup for easy environment management
- ✅ **CI/CD ready** with GitHub Actions and GitLab CI examples
- ✅ **Fast execution** (~8 seconds for full suite)
- ✅ **Isolated tests** with proper cleanup
- ✅ **Comprehensive coverage** of token lifecycle

Integration tests complement unit tests by validating actual Vault API behavior and ensuring the implementation works with a real Vault instance.

---

**Last Updated:** 2026-07-09  
**Vault Version:** 1.15  
**Python Version:** 3.13.12
