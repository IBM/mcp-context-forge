# OAuth Fetch Tools Fix

## Problem

After completing OAuth authorization, clicking "Fetch Tools from MCP Server" button failed with:
```
❌ Failed to Fetch Tools
Error: Unexpected token '<', "...
```

### Root Cause

The `/oauth/fetch-tools/{gateway_id}` endpoint requires authentication (Bearer token or JWT cookie), but after OAuth callback redirect, the browser had no authenticated session:

1. User completes OAuth flow → browser redirects to `/oauth/callback`
2. Callback exchanges code for OAuth tokens → stores in Vault
3. Callback returns HTML success page with JavaScript
4. JavaScript calls `/oauth/fetch-tools/{gateway_id}` with only CSRF cookie
5. **Endpoint rejects**: no Bearer token, no JWT cookie → 401 Unauthorized
6. Browser tries to parse 401 HTML response as JSON → parse error

## Solution

Modified `/oauth/callback` to establish a temporary authenticated session by setting a JWT cookie.

### Changes

**File**: `mcpgateway/routers/oauth_router.py`

**After successful OAuth token exchange** (lines 758-771):
```python
# Create a temporary session JWT for the user to call fetch-tools endpoint
# This JWT is short-lived (5 minutes) and scoped to just this team
from mcpgateway.utils.create_jwt_token import create_jwt_token

jwt_payload = {
    "email": app_user_email,
    "token_use": "session",
    "jti": secrets.token_urlsafe(16),
}
session_jwt = await create_jwt_token(
    data=jwt_payload,
    expires_in_minutes=5,
    teams=[team_id] if team_id else [],
)
```

**Set JWT cookie in response** (lines 906-918):
```python
# Set temporary session JWT cookie for fetch-tools API call
# Short-lived (5 minutes) and team-scoped
response.set_cookie(
    key="jwt_token",
    value=session_jwt,
    max_age=300,  # 5 minutes
    path=root_path or "/",
    httponly=True,
    secure=use_secure,
    samesite="strict",
)
```

### How It Works

1. **OAuth callback** receives authorization code + state
2. **Validates state** and extracts `team_id`, `app_user_email`
3. **Exchanges code** for OAuth access token (stored in Vault)
4. **Creates session JWT**:
   - Email from OAuth state
   - Team from OAuth state  
   - `token_use: "session"` marker
   - 5-minute expiration
5. **Sets JWT cookie** in HTML response
6. **JavaScript fetch** sends cookie automatically (`credentials: 'include'`)
7. **RBAC middleware** (`get_current_user_with_permissions`) reads JWT from cookie
8. **Fetch tools succeeds** with authenticated request

### Security Properties

✅ **Server-side token creation**: JWT created after validating OAuth state, not from client input

✅ **Team-scoped**: JWT limited to same team as OAuth flow (prevents cross-team access)

✅ **Short-lived**: 5-minute expiration (just enough for fetch-tools call)

✅ **HttpOnly cookie**: JavaScript cannot read token (XSS protection)

✅ **SameSite=strict**: CSRF protection (only same-site requests)

✅ **Secure flag**: HTTPS-only in production

✅ **Temporary**: Token expires before user might navigate away

### Alternative Approaches Considered

❌ **Skip authentication**: Would allow unauthenticated tool fetching (security risk)

❌ **Long-lived session**: Unnecessarily increases exposure window

❌ **Bearer token in HTML**: Would require JavaScript to read/store token (XSS risk)

✅ **Temporary JWT cookie**: Minimal exposure, automatic cleanup, standard auth flow

## Testing

1. Start gateway: `make dev`
2. Configure OAuth gateway with Authorization Code flow
3. Click "Authorize" → Complete OAuth flow
4. On success page, click "Fetch Tools from MCP Server"
5. ✅ Should succeed without parse errors
6. Tools should appear in gateway tools list

## Related Issues

- OAuth token storage team isolation
- Vault-backed OAuth credentials
- Multi-team OAuth support
