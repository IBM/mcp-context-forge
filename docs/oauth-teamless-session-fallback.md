# OAuth Teamless Session Fallback

## Problem

Admin UI OAuth flow was failing with:
```
❌ OAuth Authorization Failed
team_id required from JWT 'teams' claim, but user_context has no teams.
Cannot store/retrieve OAuth tokens without team context.
```

### Root Cause

**Admin UI session JWTs don't include `teams` claim**, causing two issues:

1. `TokenStorageService._get_team_id()` threw `ValueError` when no teams found
2. Vault backend couldn't construct storage path (requires team_id)

This occurred because:
- Admin UI users log in with session-based auth (not API tokens)
- Session JWTs may not include `teams` claim
- Previous code had DB fallback, but that was removed per security review (violates token scoping invariants)

## Security Constraint

**From code review**: "Remove DB team fallback from `_build_user_context()`"

**Rationale**: 
- Session tokens may have narrowed team scope (subset of DB teams)
- Re-querying DB would widen that scope back to full membership
- Violates Layer 1 token scoping security invariant

**Requirement**: Teams must come from JWT token claims, not database queries.

## Solution: Option 2 - Fallback Storage for Teamless Sessions

Implement graceful degradation when JWT has no `teams` claim:

### Behavior

| Auth Type | JWT Teams | Storage Path | Isolation |
|-----------|-----------|--------------|-----------|
| API OAuth | ✅ Present | `vault/oauth/{team_id}/...` | ✅ Team-isolated |
| Admin UI OAuth | ❌ Missing | `vault/oauth/shared/...` | ⚠️ Shared fallback |

### Implementation

**1. TokenStorageService._get_team_id()** - Return `None` instead of raising error

**Before** (lines 143-151):
```python
# No fallback - raise error if JWT teams missing
logger.error(
    "OAuth token operation requires team_id from JWT 'teams' claim..."
)
raise ValueError(
    f"team_id required from JWT 'teams' claim, but user_context has no teams."
)
```

**After**:
```python
# Fallback: return None when JWT teams missing (for Admin UI sessions without team context)
logger.warning(
    "OAuth token operation for user=%s, gateway=%s has no team_id from JWT 'teams' claim. "
    "Falling back to non-team-isolated storage (database or shared path).",
    app_user_email,
    gateway_id,
)
return None
```

**2. VaultTokenBackend Path Methods** - Handle `None` team_id

Updated signatures:
- `_construct_vault_path(team_id: str | None, ...)`
- `_construct_metadata_path(team_id: str | None, ...)`
- `_construct_credentials_path(team_id: str | None, ...)`

Path logic:
```python
team_segment = team_id if team_id else "shared"
return f"{self.mount}/data/{self.prefix}/{team_segment}/{server_id}/{email_encoded}"
```

**Examples**:
- With teams: `secret/data/contextforge/oauth/d855a360/647ad7b3/user%40example.com`
- Without teams: `secret/data/contextforge/oauth/shared/647ad7b3/user%40example.com`

## Trade-offs

### ✅ Advantages

1. **Admin UI OAuth works** - No longer blocked by missing teams
2. **API OAuth unchanged** - Still uses team-isolated paths
3. **Security invariant preserved** - No DB team lookups
4. **Graceful degradation** - System functional, not broken

### ⚠️ Disadvantages

1. **Reduced isolation** - Admin UI tokens stored in shared path
2. **Cross-team visibility** - Users in shared path can potentially access each other's tokens (if they know email/gateway)
3. **Not ideal for production** - Fallback is a compromise, not best practice

## Security Considerations

### Shared Path Risks

**Scenario**: Two users from different teams both use Admin UI OAuth for same gateway

- User A: `alice@example.com`, Team `engineering`
- User B: `bob@example.com`, Team `sales`

**Without teams (Admin UI)**:
- Both tokens stored under `vault/oauth/shared/{server_id}/`
- Path: `.../{alice%40example.com}` and `.../{bob%40example.com}`
- ✅ Isolated by email (different paths)
- ⚠️ Same Vault policy (both access `shared/*`)

**With teams (API)**:
- Alice: `vault/oauth/engineering/{server_id}/alice%40example.com`
- Bob: `vault/oauth/sales/{server_id}/bob%40example.com`
- ✅ Isolated by team + email
- ✅ Vault policies can differ per team

### Mitigation

The email-based sub-path provides basic isolation:
- Users can only access their own email path
- Vault ACLs should restrict `shared/*` to authenticated users only
- Token lookup requires exact email match

### Recommended Long-term Solution

**Option 1: Fix Admin UI Login** (preferred)
- Include `teams` in session JWT when user logs in
- Enables team-isolated storage for Admin UI OAuth
- Aligns Admin UI auth with API auth model

## Testing

### API OAuth (should work as before)
```bash
# Generate JWT with teams
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --teams team-123 \
  --exp 10080)

# Initiate OAuth
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/oauth/authorize/gateway-id

# Tokens stored at: vault/oauth/team-123/{server_id}/user%40example.com
```

### Admin UI OAuth (fallback to shared path)
```bash
# Login to Admin UI (session JWT without teams)
# Navigate to gateway → Click "Authorize"
# OAuth callback should succeed

# Tokens stored at: vault/oauth/shared/{server_id}/user%40example.com
```

### Verification
```bash
# Check Vault paths
vault kv list secret/contextforge/oauth/
# Should show both team-specific and "shared" paths

vault kv list secret/contextforge/oauth/shared/
# Shows server_ids for teamless sessions
```

## Migration Impact

### Existing Tokens

- ✅ Team-isolated tokens unchanged (API OAuth continues working)
- ⚠️ Admin UI must re-authorize (old tokens under old path)

### Vault Structure

**Before**:
```
secret/contextforge/oauth/
├── team-123/
│   └── 647ad7b3/
│       └── user@example.com
```

**After**:
```
secret/contextforge/oauth/
├── team-123/           # API OAuth (team-isolated)
│   └── 647ad7b3/
│       └── user@example.com
└── shared/             # Admin UI OAuth (fallback)
    └── 647ad7b3/
        └── user@example.com
```

## Future Improvements

1. **Add teams to session JWT** - During Admin UI login, include user's teams
2. **Team selection UI** - Let user choose which team to authorize for
3. **Audit logging** - Track usage of shared path (for compliance)
4. **Deprecate shared path** - Once session JWTs include teams, remove fallback

## Related

- Security Review: "Remove DB team fallback from `_build_user_context()`"
- Token Scoping Invariants: `docs/docs/architecture/multitenancy.md`
- OAuth Design: `docs/docs/architecture/oauth-design.md`
