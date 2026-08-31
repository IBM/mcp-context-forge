# JWT Token Security Implementation

## Overview

This document describes the comprehensive JWT token security improvements implemented to address X-Force Red security audit findings regarding session token management.

## Security Issues Addressed

### Original Issues
- **Token Lifetime**: Average TTL of ~70 days (10,080 minutes)
- **No Server-Side Revocation**: Tokens could be replayed after logout
- **No Idle Timeout**: Sessions remained active indefinitely
- **No Token Invalidation**: Old tokens remained valid when new ones were issued

### X-Force Red Recommendations Implemented
✅ Server-side token blocklist with immediate invalidation
✅ Reduced token lifetime to 5-20 minutes (configurable)
✅ Idle timeout enforcement (60 minutes default)
✅ Logout endpoint with token revocation
✅ Automatic cleanup of expired blocklist entries
✅ Redis caching for performance
✅ Comprehensive audit logging

## Implementation Details

### 1. Configuration Changes (`mcpgateway/config.py`)

New security-focused configuration options:

```python
# Session token configuration (short-lived for security)
token_expiry: int = 20  # minutes (was 10080 = 70 days)
    # Range: 5-1440 minutes
    # Recommended: 5-20 minutes for security

# Idle timeout configuration
token_idle_timeout: int = 60  # minutes
    # Range: 5-1440 minutes
    # Maximum idle time before token requires refresh

# Token blocklist cleanup
token_blocklist_cleanup_hours: int = 24
    # Range: 1-168 hours
    # Hours to retain expired tokens in blocklist before cleanup
```

### 2. Database Schema Changes (`mcpgateway/db.py`)

Enhanced `TokenRevocation` model:

```python
class TokenRevocation(Base):
    """Token revocation blacklist for immediate token invalidation."""

    jti: str  # JWT ID (primary key)
    revoked_at: datetime  # Revocation timestamp
    revoked_by: str  # Email of user who revoked the token
    reason: str  # Reason: logout, idle_timeout, security, token_refresh
    token_expiry: datetime  # Original token expiry for cleanup scheduling
    last_activity: datetime  # Last activity timestamp for audit trail
```

**Migration**: `mcpgateway/alembic/versions/aa1_add_token_revocation_idle_timeout_fields.py`

### 3. Token Blocklist Service (`mcpgateway/services/token_blocklist_service.py`)

New service providing:

- **Token Revocation**: Add tokens to blocklist with reason tracking
- **Revocation Check**: Fast lookup with Redis caching
- **Idle Timeout Tracking**: Monitor and enforce activity timeouts
- **Activity Updates**: Track last activity for idle timeout enforcement
- **Automatic Cleanup**: Remove expired tokens from blocklist
- **Audit Statistics**: Track revocation patterns and reasons

Key methods:
- `revoke_token()` - Add token to blocklist
- `is_token_revoked()` - Check if token is revoked (Redis + DB)
- `check_idle_timeout()` - Verify token hasn't exceeded idle time
- `update_activity()` - Update last activity timestamp
- `cleanup_expired_tokens()` - Remove old entries
- `get_revocation_stats()` - Get revocation statistics

### 4. Token Generation Updates (`mcpgateway/routers/email_auth.py`)

Enhanced `create_access_token()`:

```python
async def create_access_token(user: EmailUser, ...) -> tuple[str, int]:
    """Create JWT access token with security enhancements.

    Security improvements:
    - Short-lived tokens (5-20 minutes)
    - JTI for revocation tracking
    - Activity timestamp for idle timeout
    - Comprehensive audit logging
    """
    payload = {
        "jti": token_jti,  # Required for revocation
        "exp": int(expire.timestamp()),  # Short expiry
        "last_activity": int(now.timestamp()),  # For idle timeout
        # ... other claims
    }
```

### 5. Authentication Flow Updates (`mcpgateway/auth.py`)

Enhanced `get_current_user()` with:

**Blocklist Check**:
```python
is_revoked = await asyncio.to_thread(_check_token_revoked_sync, jti)
if is_revoked:
    raise HTTPException(401, "Token has been revoked")
```

**Idle Timeout Enforcement**:
```python
last_activity_ts = payload.get("last_activity")
if last_activity_ts and settings.token_idle_timeout > 0:
    idle_duration = current_time - last_activity
    if idle_duration > max_idle:
        # Revoke token and reject request
        blocklist_service.revoke_token(jti, email, "idle_timeout", ...)
        raise HTTPException(401, "Token exceeded idle timeout")

    # Update activity for valid tokens
    blocklist_service.update_activity(jti)
```

### 6. Logout Endpoint (`mcpgateway/routers/auth.py`)

New `/auth/logout` endpoint:

```python
@auth_router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Logout user and revoke session token.

    Security:
    - Adds token to server-side blocklist
    - Token cannot be reused after logout
    - Supports audit trail for security monitoring
    """
    # Extract token and JTI
    # Revoke token using blocklist service
    # Return success confirmation
```

## Security Benefits

### 1. Immediate Token Invalidation
- Tokens are revoked server-side on logout
- No replay attacks possible after logout
- Fail-secure: errors in revocation check deny access

### 2. Reduced Attack Window
- 20-minute default token lifetime (vs 70 days)
- Limits exposure if token is compromised
- Configurable based on security requirements

### 3. Idle Timeout Protection
- 60-minute default idle timeout
- Prevents abandoned sessions from remaining active
- Automatic revocation on timeout

### 4. Comprehensive Audit Trail
- All revocations logged with reason
- Activity tracking for forensics
- Statistics for security monitoring

### 5. Performance Optimization
- Redis caching for fast blocklist lookups
- Automatic cleanup of expired entries
- Minimal database overhead

## Configuration Examples

### High Security (Sensitive Applications)
```bash
TOKEN_EXPIRY=5                    # 5 minutes
TOKEN_IDLE_TIMEOUT=15             # 15 minutes
TOKEN_BLOCKLIST_CLEANUP_HOURS=12  # 12 hours
```

### Balanced Security (Standard Applications)
```bash
TOKEN_EXPIRY=20                   # 20 minutes (default)
TOKEN_IDLE_TIMEOUT=60             # 60 minutes (default)
TOKEN_BLOCKLIST_CLEANUP_HOURS=24  # 24 hours (default)
```

### Development/Testing
```bash
TOKEN_EXPIRY=60                   # 60 minutes
TOKEN_IDLE_TIMEOUT=120            # 120 minutes
TOKEN_BLOCKLIST_CLEANUP_HOURS=24  # 24 hours
```

## API Usage

### Login
```bash
POST /auth/login
{
  "email": "user@example.com",
  "password": "password"
}

Response:
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1200  # 20 minutes
}
```

### Logout
```bash
POST /auth/logout
Authorization: Bearer eyJ...

Response:
{
  "message": "Logged out successfully",
  "revoked_token": "abc-123-def-456"
}
```

### Using Tokens
```bash
GET /api/resource
Authorization: Bearer eyJ...

# Token is validated:
# 1. Signature verification
# 2. Expiry check
# 3. Blocklist check (revoked?)
# 4. Idle timeout check
# 5. Activity update
```

## Monitoring and Maintenance

### Revocation Statistics
```python
from mcpgateway.services.token_blocklist_service import get_token_blocklist_service

service = get_token_blocklist_service()
stats = service.get_revocation_stats()
# Returns: {
#   "total_revoked": 150,
#   "by_reason": {
#     "logout": 100,
#     "idle_timeout": 30,
#     "security": 20
#   }
# }
```

### Manual Cleanup
```python
service = get_token_blocklist_service()
deleted = service.cleanup_expired_tokens(hours_retention=24)
print(f"Cleaned up {deleted} expired tokens")
```

### Scheduled Cleanup
Add to cron or scheduler:
```bash
# Run daily at 2 AM
0 2 * * * cd /app && python -c "from mcpgateway.services.token_blocklist_service import get_token_blocklist_service; get_token_blocklist_service().cleanup_expired_tokens()"
```

## Security Considerations

### Token Storage
- **Never** store tokens in localStorage (XSS vulnerable)
- Use httpOnly cookies or secure session storage
- Implement CSRF protection for cookie-based auth

### Token Transmission
- Always use HTTPS in production
- Never pass tokens in URL query parameters
- Use Authorization header: `Bearer <token>`

### Error Handling
- Generic error messages to prevent information leakage
- Detailed logging for security monitoring
- Fail-secure on validation errors

### Rate Limiting
- Implement rate limiting on login endpoint
- Monitor for brute force attempts
- Consider account lockout policies

## Migration Guide

### For Existing Deployments

1. **Update Configuration**:
   ```bash
   # Add to .env
   TOKEN_EXPIRY=20
   TOKEN_IDLE_TIMEOUT=60
   TOKEN_BLOCKLIST_CLEANUP_HOURS=24
   ```

2. **Run Database Migration**:
   ```bash
   cd mcpgateway
   python -m alembic upgrade head
   ```

3. **Update Client Applications**:
   - Implement token refresh logic
   - Handle 401 errors (token expired/revoked)
   - Redirect to login on authentication failure

4. **Monitor Logs**:
   - Watch for `idle_timeout` events
   - Monitor `token_revoked` security events
   - Track revocation statistics

### Breaking Changes

⚠️ **Token Lifetime Reduced**: Existing long-lived tokens will continue to work until expiry, but new tokens have 20-minute lifetime by default.

⚠️ **Idle Timeout**: Sessions will timeout after 60 minutes of inactivity by default.

⚠️ **Logout Behavior**: Tokens are now immediately invalidated on logout (previously remained valid until expiry).

## Testing

### Unit Tests (TODO)
- Token revocation service tests
- Idle timeout enforcement tests
- Blocklist cleanup tests
- Activity tracking tests

### Integration Tests (TODO)
- Login/logout flow tests
- Token expiry tests
- Idle timeout scenario tests
- Concurrent revocation tests

### Security Tests (TODO)
- Replay attack prevention
- Token reuse after logout
- Idle timeout enforcement
- Blocklist bypass attempts

## Compliance

This implementation addresses:
- ✅ OWASP Top 10 - A07:2021 Identification and Authentication Failures
- ✅ NIST SP 800-63B - Digital Identity Guidelines (Session Management)
- ✅ PCI DSS 8.2.4 - Session timeout requirements
- ✅ X-Force Red Security Audit Recommendations

## References

- X-Force Red Security Audit Report (2026)
- OWASP Session Management Cheat Sheet
- RFC 7519 - JSON Web Token (JWT)
- NIST SP 800-63B - Digital Identity Guidelines

## Support

For questions or issues:
- Security concerns: security@example.com
- Implementation questions: See `mcpgateway/services/token_blocklist_service.py`
- Configuration help: See `mcpgateway/config.py`

---

**Last Updated**: 2026-04-21
**Version**: 1.0.0
**Status**: Implemented
