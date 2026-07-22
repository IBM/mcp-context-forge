# Vault OAuth Implementation - Changes Summary

## Code Changes Made

### 1. Simplified OAuth Callback Architecture

**File:** `mcpgateway/routers/vault_router.py`

**Changes:**
- ✅ Updated module docstring to reflect single callback endpoint
- ✅ Changed `/vault/authorize` to redirect to `/oauth/callback` instead of `/vault/callback`
- ✅ Removed entire `/vault/callback` endpoint (lines 210-477) - it was redundant
- ✅ Updated endpoint docstring to clarify callback routing

**Rationale:**
The existing `/oauth/callback` endpoint already respects `OAUTH_TOKEN_BACKEND` and stores tokens in the configured backend (database or vault). Creating a separate `/vault/callback` was unnecessary duplication.

### 2. OAuth Callback URL Construction Fix

**File:** `mcpgateway/routers/vault_router.py`

**Change:** Line ~171
```python
# Before (broken - relative path):
callback_url = f"{root_path}/vault/callback"

# After (fixed - full URL):
request_origin = f"{request.url.scheme}://{request.url.netloc}"
root_path = resolve_root_path(request) if request else ""
callback_url = f"{request_origin}{root_path}/oauth/callback"
```

**Issue Fixed:**
GitHub OAuth was rejecting the redirect because it received `/vault/callback` instead of `http://localhost:4444/vault/callback`.

## Architecture Summary

### OAuth Flows

**Flow 1: Traditional (gateway-based)**
```
Client → /oauth/authorize/{gateway_id} → OAuth Provider → /oauth/callback → Backend Storage
```

**Flow 2: Simplified (server-based)**
```
Client → /vault/authorize/{server_id} → OAuth Provider → /oauth/callback → Backend Storage
```

**Key Point:** Both flows use the **same callback endpoint** (`/oauth/callback`)

### Backend Storage

The `/oauth/callback` endpoint uses `TokenStorageService` which selects the backend based on `OAUTH_TOKEN_BACKEND`:
- `database` (default) → `DatabaseTokenBackend` → Stores in `oauth_credentials` table
- `vault` → `VaultTokenBackend` → Stores in Vault at `{team_id}/{server_id}/{email}`

## OAuth Provider Configuration

### Before (Required 2 URLs)
```
http://localhost:4444/oauth/callback
http://localhost:4444/vault/callback
```

### After (Only 1 URL)
```
http://localhost:4444/oauth/callback
```

## Testing Status

### Manual Testing ✅
- ✅ `/oauth/authorize/{gateway_id}` → `/oauth/callback` → Vault storage (working)
- ✅ `/vault/authorize/{server_id}` → `/oauth/callback` → Vault storage (working)
- ✅ GitHub OAuth redirect now uses full URL (working)

### Unit Tests
- ✅ No existing tests for vault router endpoints (none to update)
- ✅ Backend unit tests remain unchanged (`test_db_backend.py`, `test_vault_token_backend.py`)
- ✅ Integration tests remain unchanged (`test_vault_integration.py`)

## PR Description Updates

**New sections added:**
1. **OAuth flow endpoints** - Clarifies the two authorization flows
2. **OAuth Callback URL** - Documents single callback URL requirement
3. **Single callback endpoint reduces attack surface** - Added to security strengths

**Key message:**
Simplified architecture with unified callback endpoint that intelligently routes to the configured backend.

## Files Modified (Not Committed)

```
mcpgateway/routers/vault_router.py  (simplified callback routing)
```

## No Test Changes Required

The existing test suite doesn't have router-level tests for the vault endpoints, so no test updates are needed. The backend storage tests remain valid since the backend logic is unchanged.

## Verification Steps

To verify the changes work:

1. **Start server:**
   ```bash
   export OAUTH_TOKEN_BACKEND=vault
   export VAULT_ADDR=http://localhost:8200
   export VAULT_TOKEN=test-root-token
   make dev
   ```

2. **Test Flow 1 (traditional):**
   ```bash
   curl -i http://localhost:4444/oauth/authorize/{gateway_id} \
     -H "Authorization: Bearer $TOKEN"
   # Should redirect to GitHub, then callback to /oauth/callback
   ```

3. **Test Flow 2 (simplified):**
   ```bash
   curl -i http://localhost:4444/vault/authorize/{server_id} \
     -H "Authorization: Bearer $TOKEN"
   # Should redirect to GitHub, then callback to /oauth/callback
   ```

4. **Verify tokens in Vault:**
   ```bash
   vault kv list secret/contextforge/oauth
   vault kv get secret/contextforge/oauth/{team}/{server}/{email}
   ```

## Benefits of This Change

1. ✅ **Simpler OAuth provider configuration** - Only one callback URL to register
2. ✅ **Reduced code duplication** - Single callback handler for both flows
3. ✅ **Easier maintenance** - Changes to callback logic only need to happen in one place
4. ✅ **Smaller attack surface** - Fewer endpoints to secure
5. ✅ **Clearer architecture** - Backend selection is centralized in `TokenStorageService`

## Migration Notes

For users already testing the Vault OAuth feature:
- Update GitHub OAuth app to remove `http://localhost:4444/vault/callback`
- Keep only `http://localhost:4444/oauth/callback`
- Both authorization flows continue to work without code changes
