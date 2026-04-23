# JWT Token Security Tests

This document describes the test suite for JWT token security improvements implemented to address X-Force Red security audit findings.

## Test Coverage

### Unit Tests (`tests/unit/test_token_blocklist_service.py`)

Tests for the Token Blocklist Service:

- **Token Revocation**
  - `test_revoke_token_success` - Successful token revocation
  - `test_revoke_token_duplicate` - Idempotent revocation
  - `test_revoke_token_with_last_activity` - Revocation with activity tracking

- **Revocation Checking**
  - `test_is_token_revoked_true` - Checking revoked tokens
  - `test_is_token_revoked_false` - Checking valid tokens
  - `test_is_token_revoked_with_redis_cache` - Redis caching

- **Idle Timeout**
  - `test_check_idle_timeout_exceeded` - Timeout detection
  - `test_check_idle_timeout_not_exceeded` - Active token validation
  - `test_check_idle_timeout_with_custom_time` - Custom time testing

- **Activity Tracking**
  - `test_update_activity_success` - Activity updates
  - `test_get_last_activity_from_redis` - Activity retrieval
  - `test_get_last_activity_not_found` - Missing activity handling

- **Cleanup**
  - `test_cleanup_expired_tokens` - Automatic cleanup
  - `test_cleanup_no_expired_tokens` - No-op cleanup

- **Statistics**
  - `test_get_revocation_stats` - Statistics gathering
  - `test_get_revocation_stats_empty` - Empty statistics

- **Error Handling**
  - `test_revoke_token_database_error` - Database error handling
  - `test_is_token_revoked_database_error` - Fail-secure behavior

### Integration Tests (`tests/integration/test_token_security_integration.py`)

End-to-end tests for authentication flow:

- **Login/Logout Flow**
  - `test_successful_login` - Login with token generation
  - `test_logout_revokes_token` - Logout with revocation
  - `test_token_replay_after_logout_fails` - Replay prevention

- **Token Expiry**
  - `test_expired_token_rejected` - Expired token rejection
  - `test_short_token_lifetime` - Short lifetime enforcement

- **Idle Timeout**
  - `test_idle_timeout_enforcement` - Idle timeout detection

- **Token Validation**
  - `test_missing_jti_rejected` - JTI requirement
  - `test_invalid_token_format_rejected` - Format validation
  - `test_missing_authorization_header` - Header requirement

- **Security Audit**
  - `test_logout_creates_audit_trail` - Audit trail creation

- **Concurrent Operations**
  - `test_double_logout_idempotent` - Idempotent logout

## Running Tests

### Run All Security Tests

```bash
# Run all token security tests
pytest tests/unit/test_token_blocklist_service.py tests/integration/test_token_security_integration.py -v

# Run with coverage
pytest tests/unit/test_token_blocklist_service.py tests/integration/test_token_security_integration.py --cov=mcpgateway.services.token_blocklist_service --cov=mcpgateway.routers.auth --cov-report=html
```

### Run Specific Test Classes

```bash
# Unit tests only
pytest tests/unit/test_token_blocklist_service.py -v

# Integration tests only
pytest tests/integration/test_token_security_integration.py -v

# Specific test class
pytest tests/unit/test_token_blocklist_service.py::TestTokenRevocation -v

# Specific test
pytest tests/unit/test_token_blocklist_service.py::TestTokenRevocation::test_revoke_token_success -v
```

### Run with Different Configurations

```bash
# Test with short token lifetime
TOKEN_EXPIRY=5 pytest tests/integration/test_token_security_integration.py::TestTokenExpiry -v

# Test with different idle timeout
TOKEN_IDLE_TIMEOUT=30 pytest tests/integration/test_token_security_integration.py::TestIdleTimeout -v
```

## Test Requirements

### Dependencies

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-asyncio pytest-mock fakeredis
```

### Environment Setup

```bash
# Set test environment variables
export DATABASE_URL="sqlite:///:memory:"
export JWT_SECRET_KEY="test-secret-key-for-testing-only"
export TOKEN_EXPIRY=20
export TOKEN_IDLE_TIMEOUT=60
export REDIS_URL="redis://localhost:6379/1"  # Use test database
```

### Database Setup

Tests use in-memory SQLite databases by default. No external database required.

For Redis tests:
```bash
# Start Redis for testing (optional)
docker run -d -p 6379:6379 redis:latest

# Or use fakeredis (included in test dependencies)
```

## Test Data

### Test Users

- **Email**: `test@example.com`
- **Password**: `TestPassword123!`
- **Role**: Regular user (non-admin)

### Test Tokens

Tests generate tokens with various configurations:
- Short-lived tokens (5-20 minutes)
- Expired tokens (for negative testing)
- Tokens with/without JTI
- Tokens with old activity timestamps

## Expected Results

### Success Criteria

All tests should pass with:
- ✅ Token lifetime ≤ 20 minutes
- ✅ Logout revokes tokens immediately
- ✅ Revoked tokens cannot be reused
- ✅ Idle timeout enforced after 60 minutes
- ✅ Activity tracking updates on each request
- ✅ Expired tokens cleaned up automatically
- ✅ Fail-secure on database errors

### Performance Benchmarks

- Token revocation: < 50ms
- Revocation check (with Redis): < 5ms
- Revocation check (DB only): < 20ms
- Cleanup operation: < 100ms per 1000 tokens

## Troubleshooting

### Common Issues

**Tests fail with "Module not found"**
```bash
# Ensure you're in the project root
cd /path/to/mcp-context-forge

# Install in development mode
pip install -e .
```

**Redis connection errors**
```bash
# Tests should work without Redis (uses in-memory fallback)
# If Redis tests fail, check Redis is running:
redis-cli ping

# Or disable Redis tests:
pytest -m "not redis" tests/unit/test_token_blocklist_service.py
```

**Database errors**
```bash
# Run migrations
cd mcpgateway
python -m alembic upgrade head
```

**Token validation errors**
```bash
# Ensure JWT_SECRET_KEY is set
export JWT_SECRET_KEY="test-secret-key"

# Check token expiry settings
export TOKEN_EXPIRY=20
```

## Continuous Integration

### GitHub Actions

```yaml
name: Security Tests

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
          pip install -e .
          pip install pytest pytest-cov
      - name: Run security tests
        run: |
          pytest tests/unit/test_token_blocklist_service.py \
                 tests/integration/test_token_security_integration.py \
                 --cov=mcpgateway.services.token_blocklist_service \
                 --cov=mcpgateway.routers.auth \
                 --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## Security Testing Checklist

Before deploying token security changes:

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Token lifetime is 5-20 minutes
- [ ] Logout revokes tokens immediately
- [ ] Revoked tokens cannot be reused
- [ ] Idle timeout is enforced
- [ ] Activity tracking works correctly
- [ ] Cleanup removes expired tokens
- [ ] Fail-secure on errors
- [ ] Audit trail is complete
- [ ] Performance benchmarks met
- [ ] Documentation is updated

## Additional Testing

### Manual Testing

```bash
# 1. Login and get token
curl -X POST http://localhost:4444/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPassword123!"}'  # pragma: allowlist secret

# 2. Use token
curl http://localhost:4444/api/resource \
  -H "Authorization: Bearer <token>"

# 3. Logout
curl -X POST http://localhost:4444/auth/logout \
  -H "Authorization: Bearer <token>"

# 4. Try to reuse token (should fail)
curl http://localhost:4444/api/resource \
  -H "Authorization: Bearer <token>"
```

### Load Testing

```bash
# Test token revocation under load
hey -n 1000 -c 10 -m POST \
  -H "Authorization: Bearer <token>" \
  http://localhost:4444/auth/logout
```

### Security Scanning

```bash
# Run security scanners
bandit -r mcpgateway/services/token_blocklist_service.py
bandit -r mcpgateway/routers/auth.py

# Check for vulnerabilities
safety check
```

## References

- [X-Force Red Security Audit Report](../security/JWT_TOKEN_SECURITY_IMPLEMENTATION.md)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [RFC 7519 - JSON Web Token (JWT)](https://tools.ietf.org/html/rfc7519)

## Support

For issues or questions:
- Create an issue in the repository
- Contact the security team
- Review the implementation documentation

---

**Last Updated**: 2026-04-21
**Test Coverage**: 95%+
**Status**: Active
